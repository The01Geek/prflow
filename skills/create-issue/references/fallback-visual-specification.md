<!-- prflow:create-issue-ref step=fallback-visual-specification file=skills/create-issue/references/fallback-visual-specification.md start -->

## Visual-specification guidance (user-visible UI changes)

Handle the visual specification as part of this Step 2 clarification, as
prose guidance you follow, not a new hard gate:

1. Infer whether the issue involves user-visible UI changes as part of the normal scope assessment in `references/step-2-clarify.md` — an inference, not a dedicated "is this UI?" question. When the issue is obviously non-UI (a script, a config key, an internal doc, a CLI-only change), the whole path below is skipped — do not ask visual questions on a non-UI issue.
2. On a UI change, check the user-provided resources/context — pasted images, attached files, URLs, and design-tool links such as Figma — for an existing screenshot or mockup before asking for anything.
3. If a screenshot/mockup is present, record it in the issue's Visual Specification section (see `references/issue-template.md`): embed it when a hosted URL is available, otherwise reference it with a one-line note on how the implementer can obtain it. Do not then ask the user for one they already supplied.
4. If none is present, ask the user to provide a screenshot or mockup via the runner's user-question tool (the same tool Step 2 uses elsewhere).
5. If the user has none, verify the visual details with the user before finalizing the draft — pinning down, as applicable to the specific task: placement & layout, visual states (hover/focus/error/empty/loading/disabled), responsive behavior across breakpoints, and design-system/style match, plus any further visual dimension the task makes relevant. This checklist is a non-exhaustive prompt, not a fixed form: add task-specific dimensions and skip inapplicable ones.
6. Write the screenshot reference and/or the verified placement description into the Visual Specification section of the drafted issue.

A screenshot/mockup is **preferred, not mandatory** — verbal verification is an accepted substitute, so a UI issue is never blocked solely for lacking an image. If a UI-placement detail is still unresolved when the user disengages, it flows to the existing `## 🚫 Blocked` section like any other unresolved decision, per the disengagement rule in `references/step-2-clarify.md`.

<!-- prflow:create-issue-ref step=fallback-visual-specification file=skills/create-issue/references/fallback-visual-specification.md end -->
