# PRFlow Documentation Boundary

The internal documentation root (`docs/internal/`) and the published public site (`docs/external/`) are **sibling** directories; neither contains the other. Internal documentation synchronization operates within `docs/internal/` and does not touch `docs/external/`, which is customer-facing output owned by `docs-sync-external`.

When the branch changes user-visible behavior, record it as a `Public-doc impact` list in this skill's analysis output — one line per user-visible change — so the external synchronization step that runs later in the same pass can consume the list instead of re-deriving the impact from the diff.
