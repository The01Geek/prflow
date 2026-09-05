<!-- prflow:create-issue-ref step=fallback-read-only-sandbox file=skills/create-issue/references/fallback-read-only-sandbox.md start -->

Each arm below states the disposition of the artifacts it covers, and the working-file-listing arm routes every artifact Step 4 lists to its own arm above rather than supplying a default any arm can inherit. Filing is never blocked on any of them. Everything else is per-arm and stated where it applies: the failed delete is itself the signal you are in the read-only case only on the arms whose artifact has a delete-first step — the canonical-draft and dispatch-instruction writes have none, and the derivation-gate, presentation-gate and working-file-listing arms write and delete nothing of their own — and only the arms that say so report the reduced durability.

## Step 1 — the evidence artifact and the run registry

Step 1's on-entry delete and its write of `.prflow/tmp/create-issue/<slug>/issue-step1-<slug>.md`, and the helper's write of the run's `run-meta.json` registry entry, all fail the same way. Post the returned (or reconciled, or degraded-arm) Step 1 evidence as a visible inline-in-chat block in the current turn — the actual findings, not a bare claim that the pass ran — and re-post it whenever a later turn reaches a check that reads it. Do not trust any on-disk `issue-step1-<slug>.md` or `run-meta.json`; the visible block is the stand-in. With no readable registry the slug is **unestablished**, which routes to the title-derived fallback in `references/step-4-present-create.md`; the run reports the reduced durability and continues.

## Step 2 — the derivation artifact

If the write genuinely fails, say so in chat and record the derivation inline in your message as a visible block — the actual derived list, not a bare claim that you derived it; never silently skip writing it down. When the filesystem is read-only, do not trust any on-disk `issue-derivation-<slug>.md` (the failed delete may have left a stale leftover from a prior run); rely solely on the visible inline block as the gate's stand-in.

## Step 3.5 — the Steelman record

When the filesystem refuses the append of a `### pass <n>` entry to the `## Steelman record` section of `.prflow/tmp/create-issue/<slug>/issue-derivation-<slug>.md`, post the entry as a visible inline-in-chat block in the current turn — the actual per-pass fields, not a bare claim that the steelman ran — and re-post it whenever a later turn reaches the Step 3.6 entry confirmation that reads it. Do not trust any on-disk `## Steelman record` in that artifact; the visible block is the record's sole stand-in, and its in-turn posting is what lets the Step 3.6 entry confirmation proceed on this arm. Filing is never blocked.

## Revision-delta record

When the filesystem refuses the append of a revision-delta evidence line to the `## Revision-delta record` section of `.prflow/tmp/create-issue/<slug>/issue-derivation-<slug>.md`, post that line — naming its anchor — as a visible inline-in-chat block in the current turn, and do not trust any on-disk `## Revision-delta record`. The reduced durability is reported and filing is never blocked.

## Criterion disposition record

When the filesystem refuses the append of a disposition line to the `## Criterion disposition record` section of `.prflow/tmp/create-issue/<slug>/issue-derivation-<slug>.md` (the omit/merge/add grading record `references/issue-template.md` mandates per added criterion), post that line — naming the criterion it dispositions — as a visible inline-in-chat block in the current turn, and re-post it whenever a later turn reaches Step 4's presentation confirmation that reads it, and do not trust any on-disk `## Criterion disposition record`. Step 4's presentation confirmation reads that inline block as the record's sole stand-in. The reduced durability is reported and filing is never blocked.

## Step 2 / Step 3 — the derivation gate's stand-in

A visible block you posted in chat this run containing the full derived Definition of Ready — the actual list, not a bare claim of having derived it nor a pointer to earlier prose — stands in for the file. "Present" means it is in *this run's* transcript; re-post that full block in the current turn whenever you reach a check that fires there. A derivation in neither this run's file nor such a visible block means the pass did not run.

## Step 3.6 — the audit report artifact

The write fails as the delete does; fall back to a visible inline-in-chat block carrying the audit findings and verdict, and do not trust any on-disk `issue-audit-<slug>.md`.

## Step 3.6 — the canonical dispatch-instruction file

The `issue-audit-dispatch-<slug>.md` write fails exactly as the draft write does, so there is no on-disk instruction file for the auditor to hash and steering-absence is unestablished by construction on this arm. Do not trust an on-disk `issue-audit-dispatch-<slug>.md`; omit `--instructions-file` from `record-dispatch` rather than pointing it at one. The round's audit summary line carries the `audit independence unestablished` marker beside this arm's existing degraded markers, and the coverage-backed clean grounding is withheld — but filing is never blocked: the user's explicit approval still files the issue through the documented Step 4 override election.

## Step 4 — the presentation gate

In a read-only sandbox, rely solely on the visible inline-in-chat audit block re-posted this turn and do not trust any on-disk `issue-audit-<slug>.md`.

## Step 4 — the working-file listing

The failed or refused write or delete that put this run on this arm leaves the paths Step 4's listing names either missing or holding a prior run's bytes. Do not trust an on-disk copy of any artifact it names — each stands or falls on its own arm above — and re-enter no producing step on the strength of its rows. Where an arm above has already posted its artifact as a visible inline-in-chat block this run, that block is that artifact's stand-in and is re-posted in the current turn; an artifact with no such block is reported **unestablished**.

## Step 4 — the investigation-record artifact

When the filesystem refuses the `.prflow/tmp/create-issue/<slug>/issue-record-<slug>.md` write, present the record inline in chat — the actual routed-out content as a visible block — report the reduced durability, and never block filing. Publication is withheld on this arm rather than attempted: `scripts/post-issue-comment.sh` requires its body input from a file, so with no record file there is nothing to post. The inline block is the whole delivery, and the reduced-durability report names the record as unpublished. Do not trust any on-disk `issue-record-<slug>.md`; the visible inline block is the sole stand-in.

## Step 3.6 / Step 4 — the staged canonical-draft write

When the filesystem refuses the staging write of the *Staged canonical-draft write* shared procedure — `stage` cannot land the artifact — report the reduced durability (the intended bytes have no durable on-disk copy, so an interruption is unrecoverable and a partially-applied revision is undetectable across turns), present the draft from the in-context rendered bytes, and proceed — filing is never blocked on this arm. A revision write here still satisfies `record-revision`'s file-arm guard by piping the intended bytes to `--stdin-digest` from context (the flag reads stdin, never the artifact), and the resolution gate's evidence is those piped in-context bytes rather than a landed canonical file. This arm covers the draft write the other arms above do not.

<!-- prflow:create-issue-ref step=fallback-read-only-sandbox file=skills/create-issue/references/fallback-read-only-sandbox.md end -->
