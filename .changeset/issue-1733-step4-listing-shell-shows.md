---
bump: patch
type: Fixed
---

- **`/prflow:create-issue` Step 4 working-file listing now reports presence from what the shell shows.** The listing runs `ls -lL` (not `ls -l`) over its four named paths, so a path that is a symbolic link to a gone target draws a not-found message and is classified `absent` instead of passing as `present` on a stale row; a not-found message naming a path — by the whole path or by its final segment, since one `ls` quotes the operand and another names only the file name — is decisive even beside a printed row, a path is `present` only when its own row describes an ordinary file of at least one byte (a zero-byte file is `absent`), and a directory is `unestablished`. The slug-unknown arm stays on plain `ls -l` so a broken link is still shown. Re-running the derivation step now re-runs the steelman pass with it, the presentation gate is the single owner of the audit file's re-entry, and the listing names the run-state files it does not cover. (#1733)
