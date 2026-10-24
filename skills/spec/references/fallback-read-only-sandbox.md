<!-- prflow:spec-ref step=fallback-read-only-sandbox file=skills/spec/references/fallback-read-only-sandbox.md start -->

**Common rule** — every arm below applies it unless the arm states otherwise: post the artifact's current content as a visible inline-in-chat block in the current turn — the content itself, never a bare claim that the pass ran nor a pointer to earlier prose — and re-post it whenever a later turn reaches a check that reads it. Trust no on-disk copy of the artifact (a failed delete may leave a stale leftover from a prior run); the visible block is the sole stand-in. A failed write never blocks filing, never authorizes it — only Step 4's filing election files the issue — and never makes an on-disk copy current.

The failed delete is itself the signal you are in the read-only case only on the arms whose artifact has a delete-first step — the derivation-gate arm writes and deletes nothing of its own — and only the arms that say so report the reduced durability. The working-draft and title files follow Step 3's own first-write rule, a failed option-check file delete follows Step 2's *Option check*, and an audit round's return file follows `references/step-3-6-audit-dispatch.md`.

## Step 1 — the evidence artifact and the run registry

Step 1's `mkdir`, its on-entry delete and its own writes of the index and role files (a peer's failed write takes Step 1's reply-in-full arm instead), and the helper's write of the run's `run-meta.json` registry entry, all fail the same way: the common rule's block is the entire Step 1 record in one block — discovery's required fields, the concise risk report, any degraded discovery and retained risk evidence, and the role-failure notes — never the registry entry, and its distrust covers all four files. When Step 1 is on this arm before dispatch, an isolation failure included, tell both peers to reply in full, and dispatch discovery without `--report-file` and risk without a report-file path. With no readable registry the slug is **unestablished**, which routes to the title-derived fallback in the skill root's *Runner setup*; the run reports the reduced durability and continues.

## Step 2 — the derivation artifact and *Option check*

When the `issue-derivation-<slug>.md` write fails, say so in chat and apply the common rule to the actual derived list; never silently skip writing it down. A failed write of your own *Option check* posts that record the same way.

## Revision-delta record

When the filesystem refuses the append of a `kept at fork:` line to the `## Revision-delta record` section of `.prflow/tmp/spec/<slug>/issue-derivation-<slug>.md`, post that line once under the common rule, whose distrust covers any on-disk `## Revision-delta record`, and report the reduced durability.

## Step 2 / Step 3 — the derivation gate's stand-in

The common rule's block holding the full derived Definition of Ready stands in for the file; "present" means it is in *this run's* transcript. Re-post it also in the turn the `## Evidence bundle` section changes, a revision's changes and an appended settle read included; each posting carries the whole section as last changed, and only the latest posting counts. A derivation in neither this run's file nor such a visible block means the pass did not run.

## Step 4 — the investigation-record artifact

When the filesystem refuses a Step 4 `issue-record-<slug>.md` write or its leftover delete, apply the common rule at each presentation to the actual routed-out content, and report the reduced durability. Sub-step 5c posts nothing on this arm, since its helper posts only that file; the reduced-durability report names the record as unpublished.

<!-- prflow:spec-ref step=fallback-read-only-sandbox file=skills/spec/references/fallback-read-only-sandbox.md end -->
