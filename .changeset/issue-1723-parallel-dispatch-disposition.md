---
bump: patch
type: Added
---

- **The engine-ground-truth block now states, in one place, that mutually independent tool calls are issued in a single message.** Every request an agent makes re-sends the whole conversation, so calls made one per message pay a full request each for work that could have shared one. The new section renders in all three of the block's modes (`review`, `implement`, `generic`). Independence is the whole test and it fails closed: calls whose independence cannot be established are treated as dependent and stay in separate messages. It licenses no merge of dependent calls, is not a rule about writing fewer and larger edit hunks, widens no grant, and preserves the commit-before-dispatch obligation for write-capable subagent dispatches. The existing site-local batching mandates are unchanged, as the site-specific applications of it. (#1723)
