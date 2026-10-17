# Reference: Fix discipline

Search with the Grep tool, else `git grep --untracked -nP -e '<pattern>' -- :/`, escaping literal metacharacters. Report a refused search, an exit above 1 or elided output as unverified; an unverified class sweep defers its finding. Keep scratch files under an ignored path (`.prflow/tmp/` where ignored).

## Severity

Grade a finding by observable behavior on the bad input, in both directions. Failing open — admitting a wrong value, corrupting state, silently skipping a guard — supports Critical or Important. Failing closed, a failure the suite catches, or a wording-only defect is real but rarely top severity. "Documented" and "contrived" are not mildness: a guard must catch contrived inputs, and a disclosed hole is still open. Never down-grade to avoid a fix. When changing a grade, record fail direction, suite coverage and blast radius; when in doubt about a real defect, keep the higher grade.

## Writing the fix

- Prefer deletion or reuse; add text, code or tests only to close the finding, its class or a criterion. A branch, flag, warning or fallback for an input no caller sends needs that justification; files, external formats and other processes count as callers.
- A deletion strands what fed the removed code and anything that referenced it: re-read the enclosing unit and search for references. A contract change — a renamed symbol, an altered signature, a tightened validator, a moved output stream — reaches every caller, fixture and assertion: search for the old shape. A new error path or fallback leaves a specific, actionable account and never turns an error into a success-shaped value.
- Make the fix correct for every input, not only the case the reviewer described.
- Class sweep: search the defect and changed contract by affected identifiers, literals and rule subject terms in the file and coupled sites, including outside the PR delta. Inspect unclear hits; include any not ruled out. Fix related instances, leave unrelated code, and delete or point surplus restatements at their rule.
- Share the contract. Before adding a guard for a downstream operation (a parse, a decode, a date conversion, a type narrowing), name that operation and make it the guard — try it and reject on failure — or reuse the idiom already in the file. A separate validator that re-derives the operation's contract usually accepts a superset and fails open where it claims to fail closed.

## Claims

Every comment, doc, changelog or PR-body sentence the fix adds, edits, relies on or falsifies is a claim: verify it at HEAD before committing, re-reading an edited sentence whole. Check "as before", "previously" or "no longer" against the base commit (`git show <base>:<path>`), and a claim about a value against every reader of that value — search its key or literal across code, CI and config. An untrue claim is a correctness defect: delete it, else point it at its rule's home, else reword it — or fix the code when the code is wrong.

## Acceptance criteria

Check every fix, wording-only included, against each of the linked issue's acceptance criteria before committing. Decline and revert one that would weaken or contradict a criterion, recording `Disputed criterion "<criterion>": <declined findings, summarized> — amend the issue or accept the criterion.`; apply one stricter than a criterion's wording and disclose it as `Stricter than criterion "<criterion>": <case> — <why>`, `<criterion>` being the criterion's text on one line without its checkbox. Append each line to the end of the PR body: write the body `gh pr view <n> --json body --jq .body` prints plus the line to a scratch `<file>`, then `gh api --method PATCH repos/{owner}/{repo}/pulls/<n> -F body=@<file>` (`-F`; `-f` sends the literal path) and read the body back. A read-back that is not that body followed by the line (trailing newlines aside) is a failed write: redo it once. If the first read or redo fails, put the line in your report instead, restoring the first read's body if the PR body changed. Unreadable criteria: revert and defer fixes changing what a rule decides, naming what went unread; with no linked issue or criteria, the fix proceeds.

## Tests

- Honor repository requirements and criteria. Reuse coverage; add tests for consequential gaps needing recurring protection. Prefer reproducing bugs first; later tests can fail against unfixed code.
- Check behavior and distinct failures, not branch counts. Negative checks distinguish intended rejection from unrelated failure. Reuse valid controls; confirm collection and suite idioms.
- Mutate only for a false-green risk not settled by RED; prefer a disposable copy. In-place: record the file's `git hash-object --no-filters` ID and verify a matching backup at `.prflow/tmp/in-place/<repo-relative path>` before mutating. Revert your mutation and compare IDs before further edits or deleting the backup. On immediate mismatch restore the verified backup and re-check; if still mismatched, stop naming the file and both IDs. Never restore a leftover backup over later work or use `git stash` / `git checkout -- <file>` over other edits.
- Replay representative cases for consequential model-decision changes; review mechanical wording in context. Prompt delivery does not prove model behavior. Report evidence and gaps in the caller's output (standalone: final report); insufficient evidence cannot establish the required outcome.

## Deferrals

Every finding you do not fix, a pushback included, gets a durable record naming WHAT was deferred, WHY, and when to revisit it, in the first available of: your caller's decision record, a code comment at the site, a reply on the PR review thread, a linked follow-up issue. When a shipped disclosure already answers the finding, cite it by location and a short verbatim phrase, with the revisit condition "only if evidence contradicts the cited disclosure".

On a numbered pull request, a pushback because the finding is not a defect, backed by technical evidence, also gets the column-0 line `Finding rejected "<the finding, on one line>": <evidence: the file and line read and what it shows>`, appended by *Acceptance criteria*'s write path unless the body already holds it; a finding arguing against a decided criterion takes the `Disputed criterion` route instead. Before the first fix on such a pull request, read its body once as that path does; when it holds a `Finding rejected` line covering a finding you fix, the fix deletes that line by the same path: write the body that path reads without the line, and expect that body back. Report a failed pre-fix read as `Finding rejected lines unchecked`, and a line that path would put in your report as not deleted.

<!-- END fix-discipline.md -->
