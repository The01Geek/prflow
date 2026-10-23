# Writing standard for agent-authored content

How the prose you write should read — issues, review findings, workpad reflections, PR descriptions, and internal documentation.

## Your reader

A competent developer who does not know this codebase, reading English as a second language. They understand software. They do not know this repository's private terms, its issue numbers, or its internal file layout.

## The rules

1. **Use simple words.** Pick the everyday word over the sophisticated one, and the concrete noun over the abstract one: "delete", not "obviate"; "runs before", not "temporally precedes". If a plain English equivalent exists, use it. A reader who has to stop and decode a word has stopped reading.

2. **Prefer the plain long sentence to the compressed expert one.** When a shorter phrasing only lands for someone who already knows this codebase, write the longer version anyone can follow. Extra words are cheap; a reader who guesses wrong acts wrong.

3. **Open with a TLDR in plain language.**
   - Describing a change — a PR description, a review finding, a release-note entry — open with two to four sentences saying what is broken and what will change. An issue opens with the opening summary the spec issue template's Problem Statement defines.
   - Not describing a change — a reference page, or this standard — open with what the page is for and who it is for.
   - Neither opening uses a repository-private term.

4. **One claim per sentence.** A second claim goes in its own sentence.

5. **Evidence sits in its own bullet.** Put the support for a claim in a separate bullet, not nested inside the sentence it qualifies. The claim reads first; the evidence follows it.

6. **Use the standard term; define a coined one at first use.** When a word already exists for the thing, use it rather than inventing one. When you must coin one, define it where it first appears. Do not invent ALL-CAPS taxonomies, and do not attach serial tags such as `R7`, `META`, or `CORRECTION` — the surrounding structure already classifies the content.

7. **Do not hard-wrap.** Write each paragraph and each bullet as one line and let the renderer wrap it. A hand-inserted fixed-column break survives into the rendered output as a ragged short line, and it makes every later edit rewrap the whole paragraph. Line breaks inside a fenced code block are content, so leave those alone.

8. **Keep each sentence true at the scope it states.** A sentence describing what code or a rule does holds for every case its words cover. Keep a condition all those cases share in the sentence's subject ("For a clean result, …"), even where another rule asks you to give conditions only as examples. Add no limit, no only-route and no consequence the source does not have. Narrowing which cases the sentence covers is allowed: a narrower subject, a universal cut down to the members you checked, or "can" in place of "does". A qualifier on where, when or how something happens that the source does not have is an added limit: "reads the files in the repository" when the source reads them from anywhere, or "shown in the dialog" when the source also prints it in chat. A sentence naming where something appears or happens, with no "for example", is an only-route claim, and it is false when the source has another route, including a fallback or failure route you chose not to document: "the dialog shows the total" is false when a failed load prints the total in chat. Search the source for every route before naming a place, then name every route, mark the list "for example", or leave the place out. Give a list of conditions complete, or mark it "for example"; an example list still keeps the condition all its cases share. When the reader does not need the description, delete it or replace it with a pointer to a page that reader can open.

## Exempt text

Some of this content is parsed by tools. An `## Acceptance Criteria` heading, the `- [ ]` token opening a checkbox row (not the criterion text after it), an HTML marker block, and a literal token such as `PR #<N>` or a trailing `(post-merge)` tag are matched exactly by downstream code. These, and the approved or prescribed-verbatim wording the no-options rule protects, are exempt from the rules above and survive verbatim.
