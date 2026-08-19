<!-- prflow:create-issue-ref step=quality-group-visual file=skills/create-issue/references/quality-group-visual.md start -->
## Quality group — visual presentation

Trigger (observable before this reference loads): the issue involves a user-visible UI change (Step 2's visual-specification inference). A clearly non-UI issue — a script, a config key, an internal doc, a CLI-only change — does not load this group; uncertain applicability loads it.

Each obligation appears once, as its checklist row plus the rule text it carries.

- [ ] **The Visual Specification section carries what a UI change requires; non-UI issues omit it entirely.** Include a `### Visual Specification` section **only** for user-visible UI changes; omit it entirely otherwise — no "Visual Specification: none" placeholder. Record one of two things, per what Step 2 obtained from the user: **a screenshot or mockup** — embed it inline when a hosted URL is available (`![description](https://…)`), otherwise reference it with a one-line note on how the implementer obtains it (attached file name, design-tool link such as Figma); or **a verbally-verified placement spec** — the pinned-down visual details Step 2 verified with the user (placement & layout, visual states such as hover/focus/error/empty/loading/disabled, responsive behavior across breakpoints, design-system/style match, plus any task-specific dimension). Only the dimensions that actually apply appear; a screenshot is preferred, but the verbal spec is an accepted substitute.
<!-- prflow:create-issue-ref step=quality-group-visual file=skills/create-issue/references/quality-group-visual.md end -->
