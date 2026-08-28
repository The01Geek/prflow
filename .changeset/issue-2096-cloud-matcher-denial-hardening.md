---
bump: patch
type: Fixed
---

- **Hardened the review fallback marker recipe and the vendored subagent skills' extension loader against cloud matcher expansion denials.** The review skill's helper-never-ran fallback arm now composes its run-keyed progress marker by literal substitution from the already-observed `compose-run-url.sh` output instead of a `${GITHUB_RUN_ID}`/`${...:-1}` shell parameter expansion the cloud permission matcher silently denies, and both vendored subagent skills (`requesting-code-review`, `receiving-code-review`) now load their prompt extension through the vendored-literal-first conditional ladder — enrolled in `lint-anchor-fallback-arm.py` — so a cloud review run no longer loses turns to refusals that produce no output. `receiving-code-review` also gains the dispatcher-supplied-command override paragraph. (#2100)
