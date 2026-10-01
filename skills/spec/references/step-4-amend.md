<!-- prflow:spec-ref step=4-amend file=skills/spec/references/step-4-amend.md start -->

### Step 4 sub-step 5: amend an existing issue

   Amend arm (widening an existing issue). When Step 1's duplicate check found an open issue to widen rather than file a new one, instead of `gh issue create`, rewrite that issue's body in place — never a comment, which the implementing run does not read. The body file is `<bound-root>/.prflow/tmp/spec/<slug>/amend-body-<slug>.md` and the read-back file `<bound-root>/.prflow/tmp/spec/<slug>/amend-readback-<slug>.md`. On a file-arm epoch, emit, guard and send the body in one statement:
   ```bash
   python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/issue-audit-state.py emit-body "<slug>" --nonce "<nonce>" --draft-file "<absolute issue-draft-<slug>.md path>" > "<body file>" && test -s "<body file>" && gh api --method PATCH repos/{owner}/{repo}/issues/<n> -F "body=@<body file>" --silent
   ```
   On an embed or inline epoch, write the body file with the Write tool and, only after the write succeeded, send that PATCH behind the same `test -s "<body file>" &&` guard. On a tier denial of the PATCH, send through `--input` rather than iterating the denied shape — on a file-arm epoch, prefixed with the `emit-body … > "<body file>" &&` head above — where `<json file>` is `<bound-root>/.prflow/tmp/spec/<slug>/amend-body-<slug>.json`:
   ```bash
   test -s "<body file>" && "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/run-jq.sh -Rs '{body: .}' "<body file>" > "<json file>" && gh api --method PATCH repos/{owner}/{repo}/issues/<n> --input "<json file>" --silent
   ```
   Every step of a guarded send except `test -s` prints its failure, so one that exits non-zero silently means an empty or missing body file. When a step before `gh api` failed or was refused (for example `emit-body`, the Write or `test -s`), or the tier denied the `--input` statement too, no PATCH was sent: report the amend as not attempted, naming the cause, and stop. Otherwise, including when `gh api` itself failed or you cannot place the failure, read the stored body back (`--template` prints a non-empty stored body byte-exact) and hash both files in one statement:
   ```bash
   gh api repos/{owner}/{repo}/issues/<n> --template '{{.body}}' > "<read-back file>" && git hash-object --no-filters "<body file>" "<read-back file>"
   ```
   Two equal digests: the issue is widened; run sub-step 5d. Two different digests — a silent literal `@path` or truncation included — are a failed write. Fewer than two digests leave the write unverified. On a failed or unverified write, stop and report that outcome, never the issue as widened.

<!-- prflow:spec-ref step=4-amend file=skills/spec/references/step-4-amend.md end -->
