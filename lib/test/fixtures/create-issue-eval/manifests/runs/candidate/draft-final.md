# Fix stale cache after refresh

## Reproduction

1. Refresh an item and observe stale cache data.

## Acceptance Criteria

- Cache invalidation prevents stale cache reads after refresh.
- Keep a safe rollback path.

## Testing Strategy

- Reproduce the stale read, then verify the fix and rollback.
