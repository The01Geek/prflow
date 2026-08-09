# PRFlow Documentation Boundary

The internal documentation root (`docs/internal/`) and the published public site (`docs/external/`) are **sibling** directories; neither contains the other. Internal documentation synchronization operates within `docs/internal/` and does not touch `docs/external/`, which is customer-facing output owned by `docs-sync-external`.

When the branch changes user-visible behavior, record the public-doc impact in the status summary so the external synchronization step can update it separately in the same implementation run.
