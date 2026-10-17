<!-- prflow:spec-ref step=4-create file=skills/spec/references/step-4-create.md start -->

### Step 4 sub-steps 5–6: file the issue

   File a new issue, or — on a run that widens an issue under Step 1's widen rule — replace that issue's title and
   body in place, never by a comment: the body is the only channel implement takes acceptance criteria from.
   `<method>` is `POST` and `<endpoint>` is `repos/{owner}/{repo}/issues` for a new issue; on a widen they are `PATCH`
   and `repos/{owner}/{repo}/issues/<issue_number>`, `<issue_number>` being the widened issue's number. Every step
   below runs on both unless it names one.

   When the working-draft file landed, send it itself as the body; otherwise take the heredoc
   form below. The write sends no labels or assignees: sub-step 5a stamps provenance and
   sub-step 6 applies 3a's assignment answer. `<title>` is the line in
   `.prflow/tmp/spec/<slug>/issue-title-<slug>.txt` (from your message when the draft is there),
   with each `"`, `$`, backtick and `\` backslash-escaped. Send it with `-f`, not `-F`, which
   reads a leading `@` as a file:

   ```bash
   test -s "<absolute working-draft file path>" && gh api --method <method> <endpoint> -F "body=@<absolute working-draft file path>" -f "title=<title>" --jq .html_url
   ```

   On a tier denial of that send, re-send once through `--input` rather than iterating the denied shape;
   `<json file>` is `.prflow/tmp/spec/<slug>/issue-body-<slug>.json` made absolute from the working directory:
   ```bash
   test -s "<absolute working-draft file path>" && "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/run-jq.sh -Rs --arg title "<title>" '{body: ., title: $title}' "<absolute working-draft file path>" > "<json file>" && gh api --method <method> <endpoint> --input "<json file>" --jq .html_url
   ```

   A title file you cannot read is Step 3's lost-draft stop. On a non-zero exit with no output, run
   `test -s "<absolute working-draft file path>"` alone: a non-zero exit there (the working-draft file is empty or
   missing) is Step 3's lost-draft stop; otherwise the send itself failed, routed below.

   When the working-draft file never landed, send the approved body from your message instead, through a quoted heredoc
   (quoted so backticks and `$` are not expanded), its lines and `BODY` terminator unindented, and report the read-back
   comparison as not performed:

```bash
gh api --method <method> <endpoint> -F body=@- -f "title=<title>" --jq .html_url <<'BODY'
<the approved body, byte for byte>
BODY
```

   When the tier denies the `--input` re-send or the heredoc send, or a step before `gh api` printed its failure,
   nothing was sent: stop, report filing as not attempted naming the cause, and run nothing below. When `gh api` exits
   non-zero, or you cannot place the failure, stop, surface the error output verbatim, warn that the issue may already
   have been created or its title and body replaced so the user checks the issue before re-running, report both 3a answers as not applied, and run nothing below.
   Otherwise report the issue URL that `gh` prints; for a new issue, capture its number from the URL's trailing path
   segment (e.g. `…/issues/42` → `42`) — sub-steps 5a–6 need it.

   After a send from the working-draft file, read the stored body back, digest it and print the stored title;
   `<read-back file>` is `.prflow/tmp/spec/<slug>/issue-readback-<slug>.md` made absolute from the working directory:
   ```bash
   gh api repos/{owner}/{repo}/issues/<issue_number> --template '{{.body}}' > "<read-back file>" && git hash-object --no-filters "<read-back file>" && gh api repos/{owner}/{repo}/issues/<issue_number> --template '{{.title}}'
   ```
   Report in the final outcome whether that digest equals the working-draft file's digest from sub-step 3 of the
   approved presentation and the printed title equals the title file's line; when either differs, name the read-back
   file there. Fewer than two digests, or no printed title, leave the comparison not performed; report that, naming the
   failure. Continue to sub-step 5a whatever the comparison found.
5a. Stamp the `PRFlow` provenance label (best-effort); the helper creates the label if missing and prints one outcome
    token:
   ```bash
   "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-labels.sh <issue_number> PRFlow
   ```
   Any result but `applied`, no output included, goes in the final outcome as
   `PRFlow label NOT applied (<token, error, or no output>)`. Continue to sub-step 5b.
5b. Register declared prerequisites as GitHub-native blocked-by dependencies (best-effort). Run the helper as the
    command's **leading token**; it reads the filed body's `## Dependencies` section, always exits 0, and leaves
    `apply-issue-dependencies.py:`-prefixed stderr breadcrumbs:
   ```bash
   "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-issue-dependencies.py <issue_number>
   ```
   Route on its last line. `… declares no prerequisites …` means none to register. `… done for #<n>: …` means
   registration ran: name in the final outcome its `failed:` numbers and every earlier `skipped` line; the rest are
   linked. A `… missing or non-numeric issue-number argument …` line is a caller arg-slip — re-emit the call once with
   `<issue_number>`. Any other line, or no output, means prerequisites NOT registered: name that line, or its
   absence, in the final outcome. On a widen, the final outcome also says that a blocked-by link only the old body
   declared stays registered, since the helper only adds links. Continue to sub-step 5c.
5c. Publish the investigation record (sub-step 2's record file) as a comment on the issue, before sub-step 6's
    implement offer. When this run's record-file write did not land or its leftover delete was refused, invoke nothing
    and report the record not posted because its save failed. Otherwise run the bundled helper once:
   ```bash
   python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/build-investigation-record.py --issue <issue_number> --record ".prflow/tmp/spec/<slug>/issue-record-<slug>.md" --derivation ".prflow/tmp/spec/<slug>/issue-derivation-<slug>.md"
   ```
   Pass `--derivation ""` when this run's writes to the derivation artifact were refused, so an earlier run's artifact
   is never read; never read the artifact yourself. The helper applies the `spec.investigation_record_enabled` gate,
   appends the artifact's `Considered-and-rejected:` line and posts. Name its one stdout line (its docstring lists them)
   with any stderr, or that it printed none, in the final outcome, then continue to sub-step 5d whatever it printed.

6. **Apply 3a's counted answers.** Runs only after the send succeeds and the URL has been reported; it asks nothing.
   Per question, a no, an unanswered question or a discarded answer adds no assignee (reported as *issue filed,
   no assignee added*) or posts no comment; a withheld offer posts none and is reported as withheld.
   - **Assign — yes:** read the login with `gh api user --jq .login`, then
     `gh api -X POST repos/{owner}/{repo}/issues/<issue_number>/assignees -f "assignees[]=<login>"` — two commands,
     transcribing the printed login. Keep the literal `{owner}/{repo}` placeholders (never `$GITHUB_REPOSITORY`, which
     is empty off Actions) and never `gh issue edit --add-assignee` (GraphQL; fails silently under a repo-scoped token).
     A failed assignment never blocks and is named in the final outcome (*issue filed, NOT assigned*).
   - **Implement — yes** (after sub-step 5c):
     `gh api --method POST repos/{owner}/{repo}/issues/<issue_number>/comments -f "body=/prflow:implement <issue_number>" --silent`, the bare trigger with no `@claude` mention. Report that the comment was posted and that it fires the implement
     run only when the repo's devflow workflows are enabled and the commenter is authorized — both enforced by the
     `gate` job in `.github/workflows/devflow-implement.yml` (authorization via `scripts/resolve-implement-trigger.sh`). If the comment fails, surface its error and report that the issue was filed but the comment could not be
     posted. This run never starts implementation itself — implement must begin in a fresh-context agent.

<!-- prflow:spec-ref step=4-create file=skills/spec/references/step-4-create.md end -->
