# Fix stale cache after refresh

## Context

Refreshing an item can leave stale cache data visible to the next reader. The change must perform cache invalidation at the refresh boundary.

## Reproduction

1. Refresh an existing item.
2. Read the item again and observe the stale cache value.

## Acceptance Criteria

- Refreshing an item invalidates its stale cache entry.
- Operators have a documented rollback path.

## Testing Strategy

- Add a regression test that reproduces the stale read and verifies cache invalidation.
- Exercise the rollback path.
