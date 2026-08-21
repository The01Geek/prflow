---
bump: patch
type: Fixed
---

- **Sign the credential refresher's JWT without `openssl` process substitution, so long cloud
  runs keep GitHub write access on non-Linux self-hosted runners.** The refresher signed its
  App JWT with `openssl dgst -sha256 -sign <(…)`, a `/dev/fd` process-substitution path a
  native-Windows `openssl` cannot open, so a run outliving the App token's hour silently lost
  both write credentials. Signing now runs through a standard-library Python signer
  (`scripts/sign-jwt-rs256.py`, RSASSA-PKCS1-v1_5, key read only on stdin) that works across the
  runners `runs-on` can select and whose output is byte-equal to `openssl`. Each writer
  workflow's Start step now runs a synchronous pre-launch self-test that fails the job
  immediately on a signing fault; the clock read and the teardown's log read fail closed on a
  missing tool; and the refresher's token file, pidfile and log are job-scoped so the loop
  retires itself once its job is gone and a cross-job reaper retires an orphaned refresher
  whose identity it can confirm. (#1884)
