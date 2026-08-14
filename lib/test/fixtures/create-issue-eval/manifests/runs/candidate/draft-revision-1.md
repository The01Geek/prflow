# Fix stale cache after refresh

## Reproduction

1. Refresh an item and observe stale cache data.

## Acceptance Criteria

- Invalidate the cache during refresh.
- Keep rollback safe.
