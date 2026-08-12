---
bump: patch
type: Changed
---

- **The shared writing standard now leads with plain language.** `lib/writing-standard.md` drops the two paragraphs that justified its own existence and adds two rules in their place: use everyday words rather than sophisticated ones, and prefer a longer plain sentence to a shorter one only a reader who already knows the codebase could act on. The reader it names is a competent developer who has not seen this codebase and reads English as a second language. The file is ~17% shorter, and it is read fresh at every compose point across the issue, PR-description, docs, review, and retrospective skills.

- **`/prflow:create-issue` clarification questions now carry plain-language background.** Step 2 states the shape of a question — background, then the question, then the options — and where the background goes: one or two sentences open the question text itself, while a longer background, or one covering a whole batch of questions, is posted in chat immediately before the tool call, since the question tool has no background field and truncates long text. A short concrete example is added wherever one makes a choice clearer than a description does.
