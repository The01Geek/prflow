---
bump: patch
type: Changed
---

- **`verification-flight.py claim --help` is now the single source of the declaration example.** The claim help epilog renders a complete, copyable declaration (built from the required-key constants so it cannot drift from the validator) plus the four constraints the validator enforces but the help never stated — `schema_version` is the integer 1, `external_services` must be `"none"`, the four checkout object-id fields are lowercase hex (length 40 for SHA-1, 64 for SHA-256) from `checkout-fingerprint.py`, and `candidate_identity` comes from `reception-record.py`. `checkout-fingerprint.py` gains a minimal argument parser: `--help` describes its five fingerprint fields and their ledger relationship instead of printing a fingerprint, an unrecognized argument is refused, and the no-argument path is unchanged. The duplicated JSON template in the implement phase file is replaced by a pointer to the help output. (#2108)
