---
bump: patch
type: Added
---

- **The engine-ground-truth block now states, in one place, that mutually independent tool calls are issued in a single message.** Every request an agent makes re-sends the whole conversation, so its cost tracks the context it carries rather than the work it asks for, and calls made one per message pay a full request each for work that could have shared one. The new section is tier-agnostic, so review, implement and generic runs all carry it. Independence is the whole test and it fails closed: calls whose independence cannot be established are treated as dependent and stay in separate messages. The section licenses no merge of dependent calls, says nothing about writing fewer and larger edit hunks, grants no command head, shape or path the block did not already grant, and leaves the commit-before-dispatch obligation for write-capable subagent dispatches where each dispatch point defines it. The existing site-local batching mandates in the review and implement phase files are unchanged, as the site-specific applications of it. (#1723)
