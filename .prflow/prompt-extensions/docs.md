# Release-notes step is disabled in this repository

Skip Step 3 (Generate Release Notes) entirely: do not invoke the `docs-release-notes` skill. Release-notes entries here are derived at merge time from `customer-visible: true` changesets by the version-consolidate workflow, so authoring one per PR would produce a duplicate.

When you note context to carry forward between steps, record that Step 3 was deliberately skipped for this reason — a context-compacted run that loses this note may re-invoke `docs-release-notes`.

In the Final Summary, report Step 3 as skipped with the reason "release notes derived at merge time from `customer-visible: true` changesets".
