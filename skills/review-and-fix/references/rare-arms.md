# Reference: Rare Arms (read only when one fires)

A hot reference sends you here by section name when its arm fires. Read this file whole, then act on that section alone.

## Branch recovery

`entry-close` printed `branch-mismatch`. With a clean tree (`git status --porcelain` prints nothing) run `git checkout <branch>`, then re-check:

```bash
git rev-parse --abbrev-ref HEAD ; echo "branch-check-done"
```

A match records `branch-check: restored <from-ref> -> <branch>` and re-runs `entry-close`. A dirty tree, a failed checkout, a re-check still unequal, no output, or `branch-unestablished` → stop at non-convergence naming both refs, with no fix commit — on either entry.

## Inline engine

The engine dispatch was refused, or `entry-close` graded its return `unavailable`, `missing` or `malformed`. Keep the dispatch's `dispatch_mode` and `dispatch_disposition` for the record, re-run `entry-open`, Read `<loop-skill-dir>/references/engine-entry.md` and execute it yourself with the same operands — after its engine-root read and before Phase 0, run that root's *Consumer prompt extension (load first)* block on the first inline entry and its *Prompt-extension re-load at re-entry* rule on a later one — then run `entry-close` again and scan and route it as the *Engine entry*'s item 3 does; a second failure of any kind is the entry's failure route. Never run the engine inline instead of dispatching; a whole-engine failure is never the Phase-3 INCONCLUSIVE-and-proceed case.

## Criterion conflicts

A finding or checklist FAIL a prior iteration's criterion-conflict row declined (the same criterion line, and the same finding by Phase 3.2's same-finding rule or a checklist item sharing its `claim_signature`) copies that row into this iteration under its current `finding_id`, evidence verbatim, and gets no edit for the rest of the run; so does its item-3 sibling. A fix stricter than a criterion's wording is applied and disclosed in the PR body as `fix-discipline.md` states; with no PR, no disclosure.

## CONFLICT checkpoint

`update-branch-checkpoint.sh` printed `CONFLICT`: resolve the conflicts, never by hand-merging a generated or derived artifact (regenerate it from its source); if you cannot establish whether the conflicted file is generated, stop and mark it needs-human-reconciliation rather than hand-merging. Run the suite, commit, push, and record the conflicted files; a resolution the suite fails is aborted (`git merge --abort`) and the run stops. `MERGE_IN_PROGRESS` touched nothing: the run stops, with no push.

## Over-grade gate

Decide outcome 2 would promote a whole new iteration plus a re-shadow on a reviewer's emitted `Critical`/`Important` label, and the loop trusts an emitted severity in neither direction without a recorded technical evaluation. Before a new `Critical`/`Important` shadow Phase 3 finding the shadow's `criterion_exempt` does not list drives that promotion, flag it as a suspected over-grade when it matches a shape — keyed on observable signals, never a re-judgment of merits:

1. Suite-RED or fail-closed defect graded above its blast radius — the project's test suite catches its failure RED, or the code fails closed on the bad input (aborts, refuses, returns the safe value). A fail-open defect — one that admits a wrong value, corrupts state or skips a guard on the triggering input — never matches, however exotic the input or whatever a comment disclosed.
2. Diagnostic-or-cosmetic-only finding with no behavioral fail-direction — its whole observable impact is the wording of a message, breadcrumb, log, comment or other diagnostic surface. A diff-added or diff-modified doc line, code comment, example or command form is never this shape.
3. Uncorroborated single-source finding from an empirical over-grader — raised by one agent, `silent-failure-hunter` or `pr-test-analyzer`, with no other agent's finding or checklist FAIL covering the same defect.

The gate flags and requires a recorded technical evaluation; it never auto-demotes. The evaluation is a `severity-calibrated` `fix_decisions` row (`fixing.md` item 2's shape) written before promotion, whose `evidence` names the matched shape, the fail-direction, what the suite catches RED, and the blast radius; it promotes the finding at its calibrated severity, or calibrates it down. A Phase 3 finding the shadow's report caps under review Phase 4.1.5's behavior-inert prose cap (its inertness annotation records `first-conjunct=held` and `limb-one=held`) is calibrated to the cap's grade with that evidence; one capped at Suggestion cannot drive the promotion. A flagged finding with no recorded evaluation neither promotes nor is dropped (`loop-exit.md` *Over-grade gate non-convergence*). Record one `## PRFlow Reflections` bullet per flagged finding with its evaluation and calibrated severity, and state a calibration in the verdict.

<!-- END rare-arms.md -->
