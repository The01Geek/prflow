# Workpad and resume behavior

This page explains how PRFlow carries state across phases, comments, and resumed runs.

## Current behavior

The implement and review workflows write durable workpad or progress artifacts that identify the run, its phase, its status, its evidence, and its next handoff. Resume logic reads those artifacts and the current repository state before continuing; it does not assume that the last assistant message or a stale comment proves the run completed.

Workpad comments are also part of the trigger boundary. The workflow distinguishes a PRFlow workpad from a user-issued command so the system does not self-trigger from its own progress output.

## Progress notes

A run records free-text progress through `## Progress` note bullets. Two channels append them:

- `--note TEXT` — appends a note bullet whose text is taken verbatim from the argument. May be passed several times in one update; the entries share a single timestamp and are appended in one atomic PATCH.
- `--note-file PATH` — appends a note bullet whose text is read verbatim as UTF-8 from `PATH` (or from stdin when `PATH` is `-`), bypassing shell interpolation. Use it for text containing backticks, `$`, or double quotes; compose the payload file with an editor or Write tool rather than a shell heredoc or redirect, or the interpolation hazard just moves upstream. It combines with `--note`, appending after any inline `--note` bullets. An unreadable path, an undecodable (non-UTF-8) payload, or an empty/whitespace-only payload aborts the call before any PATCH.

Each note bullet renders as `{indent}- HH:MM:SS — {note}`, timestamped with a time-only UTC `HH:MM:SS` stamp and nested under the current Status's phase inside `## Progress`. A multi-line note keeps its continuation lines. The replay-dedup comparison matches a stored note by whole-line equality of the captured text (plus, for a multi-line note, its continuation lines), so it fails toward re-appending rather than risk a silent deletion. Beyond caller-supplied notes, the tool composes its own Progress rows through the same renderer — the review-coverage and disposition rows, scope-decision records, deferred-filed markers, checkpoint rows, and the completion-verification row.

## Size limits

Because a workpad is a single GitHub issue comment, `scripts/workpad.py` enforces two size limits — both measured over UTF-8 bytes with `len(text.encode('utf-8'))`, never a shell character or word counter — so an oversize write is refused with a clear message instead of being rejected by GitHub and replayed forever:

- **Per-note budget: 2,048 bytes.** A single caller-supplied Progress note (via `--note` or `--note-file`) whose UTF-8 byte length exceeds 2,048 bytes is refused, raising `_UpdateError` before any PATCH; the message names the measured byte count and the budget. A note of exactly 2,048 bytes is accepted. The budget is measured per note, so an invocation carrying several notes each within budget is accepted. The check runs over the caller's own notes *before* the failed-write buffer replay fold, so two populations are exempt — the run can shorten neither: the Progress rows the tool composes for itself, and notes the failed-write buffer replays (a note buffered before this change can therefore never wedge the workpad permanently).
- **Comment-body cap: 65,536 bytes.** Any workpad body whose UTF-8 byte length would exceed 65,536 bytes is refused before the PATCH — on the `update` inline PATCH route and on both branches of `_patch_comment_body` (in-memory text and file `body_path`), so neither route can issue an oversize PATCH. The message names the byte count, the 65,536 limit, and states that the count is a byte count. GitHub's real comment cap is 65,536 *characters*; enforcing the same number over UTF-8 bytes is a conservative pre-check, since the byte length is never smaller than the character count.

Neither refusal rewrites text, which keeps the verbatim replay-dedup comparison valid against workpads written before these checks existed. A write refused by either size check leaves no entry in the failed-write buffer, so refused content is never replayed. These checks do not rescue a workpad already at the limit; recovering one is out of scope.

## Why it works this way

Long-running agent workflows cross context, tool, and process boundaries. A durable state record makes progress inspectable and gives a resumed run a concrete comparand for deciding whether it can continue, must re-run a gate, or must stop.

## Boundaries and failure paths

- A missing, malformed, or mismatched workpad is unestablished state.
- A terminal status without its required evidence is not a completed run.
- A progress comment is not a substitute for the workpad's machine-readable state.
- Concurrent runs are deduped or reconciled according to the command and run identity; a later comment cannot silently rewrite an earlier run's evidence.

## Source of truth

- `scripts/workpad.py` — workpad parsing, writing, ticking, and terminal-state validation.
- `skills/implement/SKILL.md` and `skills/review/SKILL.md` — run-specific artifacts.
- `scripts/update-branch-checkpoint.sh` and `scripts/verification-flight.py` — checkpoint and verification state.
- `.github/workflows/devflow.yml` and `.github/workflows/devflow-implement.yml` — cloud persistence and resume entry points.
- [`docs/internal/workflow-triggers.md`](../workflow-triggers.md) — comment and dedupe behavior.

## Related topics

- [Implement](../skills/implement.md)
- [Review-and-fix](../skills/review-and-fix.md)
- [Delivery lifecycle](delivery-lifecycle.md)
